#!/usr/bin/env python3

"""
Template IAS0060 home assignment 4 Project 1 (SCITOS).
Reused by team 3 towards implementation of home assignment 6 Project 1 (SCITOS).

@author: Christian Meurer
@date: February 2022

Update: complete of task 7 - Localization 2
Team: Scitos group 3
Team members: Benoit Auclair; Michael Bryan
Date: March 30, 2022
"""
import numpy
import yaml
from copy import deepcopy
from laser_line_extraction.msg import LineSegmentList
from laser_line_extraction.msg import LineSegment
import numpy as np
from numpy.linalg import norm as norm
from numpy.linalg import det as matrix_det
from numpy.linalg import inv as matrix_inv
from numpy import arctan2 as atan2
import rospy
from tf.transformations import euler_from_quaternion, quaternion_from_euler
# from tf import allFramesAsYAML
from geometry_msgs.msg import Pose, PoseStamped, Point, Quaternion, Twist
from visualization_msgs.msg import Marker
from nav_msgs.msg import Odometry
from std_msgs.msg import Header, ColorRGBA
from coordinate_transformations import grid_to_world


class NoiseModel:
    """
    Class implementing the estimation of the error on the control inputs to the robot
    @input: control inputs as numpy array, parameters of noise model
    @output: estimate of error on control inputs
    """

    def __init__(self):
        """
        Initializes the noise model
        @param: alpha - 4 x 1 array of parameters to estimate the error on v, w
        @result: class initialization
        """
        # fetch noise model from ros parameter server
        alpha = rospy.get_param("/noise_model/alpha")
        # alpha = [1, 1, 1, 1]
        self.alpha1 = alpha[0]
        self.alpha2 = alpha[1]
        self.alpha3 = alpha[2]
        self.alpha4 = alpha[3]

    def estimateError(self, v, w):
        """
        This method updates the estimated error given the control inputs.
        @param: 2 control inputs for which there is a level of uncertainty
            v: linear speed w.r.t. x-axis in robot frame
            w: angular speed w.r.t. z-axis in robot frame
        @result: estimated error in a 2 x 2 numpy array
        """
        # compute error given control input
        next_error = np.zeros((2, 2))
        next_error[0, 0] = self.alpha1 * np.power(v, 2) + self.alpha2 * np.power(w, 2)
        next_error[1, 1] = self.alpha3 * np.power(v, 2) + self.alpha4 * np.power(w, 2)

        return next_error


class MotionModel:
    """
    Class implementing the motion model to estimate the robot's state
    @input: control inputs as numpy array
    @output: pose estimate
    """

    def __init__(self, dt):
        """
        Function that ...
        @param: dt - time step (in seconds) to estimate the system's next state
        @param: alpha - parameters to feed in to the noise model
        @result: class initialization
        """
        ### class arguments
        # time step
        self.dt = dt
        self.noise_model = NoiseModel()

        # initialization of the Jacobians
        self.jacobian_G = np.zeros((3, 3))
        self.jacobian_V = np.zeros((3, 2))

        # the diagonal is always one
        self.jacobian_G[0, 0] = 1
        self.jacobian_G[1, 1] = 1
        self.jacobian_G[2, 2] = 1

        # keep track of control input history to calculate acceleration
        self.last_control_input = np.zeros((2, 1))


    def predictPose(self, control_input, last_pose):
        """
        This method updates the predicted robot pose.
        @param: control_input - numpy array of dim 2 x 1 containing:
            *linear speed w.r.t. x-axis in robot frame
            *angular speed w.r.t. z-axis in robot frame
        @result: returns:
            *predicted pose in a 3 x 1 numpy array containing x, y, psi
            *estimated error on the control inputs in a 2 x 2 numpy array containing the covariance matrix
        """
        # extract velocities v, w
        v = control_input[0]
        w = control_input[1]

        # estimate acceleration
        a = control_input - self.last_control_input

        # calculate the step magnitude
        increment = np.array([(v + a[0, 0] * self.dt) * self.dt * np.cos(last_pose[2] + w * self.dt / 2),
                              (v + a[0, 0] * self.dt) * self.dt * np.sin(last_pose[2] + w * self.dt / 2),
                              w * self.dt + a[1, 0] * np.power(self.dt, 2)], float).reshape(3, 1)

        # add step size to previous pose
        next_pose = last_pose + increment.reshape(3, 1)

        # estimate error
        next_error = self.noise_model.estimateError(v, w)

        # compute the jacobians
        self.computeJacobian(v, w, last_pose)

        self.last_control_input = control_input

        return next_pose, next_error, self.jacobian_G, self.jacobian_V

    def computeJacobian(self, v, w, last_pose):
        """
        This method computes the Jacobians of the kinematic model.
        @param:
            *v: linear speed w.r.t. x-axis in robot frame
            *w: angular speed w.r.t. z-axis in robot frame
        @result:
            *self.jacobian_G: Jacobian with respect to the state estimate
            *self.jacobian_V: Jacobian with respect to the control inputs
        """
        # dg_x / d_psi = -v * dt * sin(psi_t-1 + w_t * dt / 2)
        self.jacobian_G[0, 2] = -1 * v * self.dt * np.sin(last_pose[2] + w * self.dt / 2)

        # dg_y / d_psi = v * dt * cos(psi_t-1 + w_t * dt / 2)
        self.jacobian_G[1, 2] = v * self.dt * np.cos(last_pose[2] + w * self.dt / 2)

        # dg_x  / d_v = dt * cos(psi_t-1 + w_t * dt / 2)
        self.jacobian_V[0, 0] = self.dt * np.cos(last_pose[2] + w * self.dt / 2)

        # dg_x  / d_w = -v * dt^2 * sin(psi_t-1 + w_t * dt / 2)
        self.jacobian_V[0, 1] = -1 * v * np.power(self.dt, 2) * 0.5 * np.sin(last_pose[2] + w * self.dt / 2)

        # dg_y / d_v = dt * sin(psi_t-1 + w_t * dt / 2)
        self.jacobian_V[1, 0] = self.dt * np.sin(last_pose[2] + w * self.dt / 2)

        # dg_y / d_w = -v * dt^2 * sin(psi_t-1 + w_t * dt / 2)
        self.jacobian_V[1, 1] = v * np.power(self.dt, 2) * 0.5 * np.cos(last_pose[2] + w * self.dt / 2)

        # dg_psi / d_w = dt
        self.jacobian_V[2, 1] = self.dt


class KalmanFilter:
    """
    Class called by the main node and which implements the Kalman Filter
    @input: control inputs as numpy array
    @output: pose estimate
    """

    def __init__(self, dt, initial_pose):
        """
        Method that initializes the class
        @param: dt - time step (in seconds) to feed to the motion model
        @param: initial_pose - robot's initial pose when the environment is launched
        @param: alpha - parameters to feed in to the noise model
        @result: class initialization
        """
        ### class arguments
        self.dt = dt
        self.motion_model = MotionModel(self.dt)

        # pose initialized at world origin
        self.last_state_mu = initial_pose

        # covariance on initial position is null because pose comes from ground truth
        self.last_covariance = np.zeros((3, 3))

        # robot doesn't move at t = 0
        self.last_control_input = np.zeros((2, 1))

        # sensor noise model
        self.sensor_covariance = np.diag(rospy.get_param("/sensor_noise_model/variances"))
        # self.sensor_covariance = np.diag([1, 1, 1])
        print("sensor covariance matrix : ", self.sensor_covariance)

    def predictionStep(self, control_input):
        """
        This method predicts what the next system state will be.
        @param: control_input - numpy array of dim 2 x 1 containing:
            *linear speed w.r.t. x-axis in robot frame, v
            *angular speed w.r.t. z-axis in robot frame, w
        @result: the method returns:
            *next_state - numpy array of dim 3 x 1 containing the 3 tracked variables (x,y,psi)
        """
        # compute the next state i.e. next robot pose knowing current control inputs
        next_state_mu, next_error, jacobian_G, jacobian_V = self.motion_model.predictPose(control_input,
                                                                                          self.last_state_mu)

        # compute covariance on the state transition probability
        covariance_R = jacobian_V @ next_error @ jacobian_V.T
        next_covariance = jacobian_G @ self.last_covariance @ jacobian_G.T + covariance_R

        # store current state estimate, covariance, control inputs
        # for use in the next iteration
        self.last_state_mu = next_state_mu
        self.last_covariance = next_covariance
        self.last_control_input = control_input

        return self.last_state_mu

    def correctionStep(self, map_features, z_i):
        """
        This method corrects the state estimate and covariance from the motion model based on current measurements
         @param:map_features: numpy array of dim (k, 3) containing a subset of k features from the map, which are good
            candidates that may be observed given current robot pose, and where axis 1 contains in order m_x, m_y, m_s

         @param:z_i: numpy array of dim (i, 3) containing i features extracted from the laser readings,
            where the axis 1 contains in order r, phi, s

        This method computes the following:
            *z_hat: numpy array of dim (k, 3) containing the predicted measurements,
            where the axis 1 contains in order r, phi, s

            *jacobian_H: numpy array of dim (k, 3, 3) containing the jacobian of the predicted measurements

            *innovation_S: numpy array of dim (k, 3, 3) containing the innovation matrix of the predicted measurements

            *self.last_covariance: covariance of state variables corrected by the measurements

        @result: the method returns self.last_state_mu: the state estimate corrected by the measurements
        """
        ### initialize matrices and indices ###

        # number of predictions to be computed
        number_pred = np.shape(map_features)[0]

        # number of observations made
        number_obs = np.shape(z_i)[0]

        # z_hat: numpy array of dim (k, 3) containing the predicted measurements
        z_hat = np.zeros_like(number_pred)

        # jacobian_H: numpy array of dim (k, 3, 3) containing the jacobian of the predicted measurements
        jacobian_H = np.zeros((number_pred, 3, 3))

        # innovation_S: numpy array of dim (k, 3, 3) containing the innovation matrix of the predicted measurements
        innovation_S = np.zeros((number_pred, 3, 3))

        ### compute predicted measurements and corresponding jacobian ###

        # compute r of each predicted measurements
        # norm-2 of the vector from robot's pose to landmark
        delta_x = (map_features[:, 0] - self.last_state_mu[0])
        delta_y = (map_features[:, 1] - self.last_state_mu[1])
        z_hat[:, 0] = norm(np.array([delta_x, delta_y]), axis=0)

        # compute partial derivatives of r
        # dr/du_x = 0.5 * (1/r) * -2 * (m_x - u_x)
        # dr/du_y = 0.5 * (1/r) * -2 * (m_y - u_y)
        jacobian_H[:, 0, 0] = -1 * np.divide(delta_x, z_hat[:, 0])
        jacobian_H[:, 0, 1] = -1 * np.divide(delta_y, z_hat[:, 0])

        # compute phi
        z_hat[:, 1] = atan2(delta_y, delta_x) - self.last_state_mu[2]

        # compute partial derivatives of phi as per the chain rule
        # and the formula of the partial derivatives given on wikipedia: https://en.wikipedia.org/wiki/Atan2
        # dphi / du_x = datan2 / ddelta_x * ddelta_x / du_x = -1 * delta_y / (delta_x^2 + delta_y^2) * -1 = delta_y / (delta_x^2 + delta_y^2)
        # dphi / du_y = datan2 / ddelta_y * ddelta_y / du_y = delta_y / (delta_x^2 + delta_y^2) * -1 = -1 * dphi / du_x
        # dphi / du_psi = -1
        jacobian_H[:, 1, 0] = np.divide(delta_y, np.power(delta_x, 2) + np.power(delta_y, 2))
        jacobian_H[:, 1, 1] = -1 * jacobian_H[:, 1, 0]
        jacobian_H[:, 1, 2] = -1

        # compute s
        z_hat[:, 2] = map_features[:, 2]

        ### compute innovation matrices and initialize its inverse ###

        jacobian_H_transposed = np.transpose(jacobian_H, axes=[0, 2, 1])
        innovation_S = jacobian_H @ self.last_covariance @ jacobian_H_transposed + self.sensor_covariance
        innovation_S_inv = np.zeros_like(innovation_S)

        ### compute the likelihood score ###

        # pre-compute scaling factor of formula upfront
        determinant = matrix_det(innovation_S)
        # if determinant = 0 we set to 1 to avoid division by zero
        determinant[determinant == 0] = 1
        scaling_factor = np.power(2 * np.pi * matrix_det(determinant), -0.5)

        # pre-compute inverted innovation matrix upfront
        # catch error if matrix can't be inverted
        for prediction in range(np.shape(z_hat)[0]):
            try:
                innovation_S_inv[prediction, :, :] = matrix_inv(innovation_S[prediction, :, :])
            except np.linalg.LinAlgError:
                innovation_S_inv[prediction, :, :] = np.eye(np.shape(innovation_S_inv)[1])

        ### correction of state estimate and covariance ###

        # for each observed feature
        # a likelihood score is computed w.r.t. each feature in the map
        # the kalman gain is computed for this observation
        # the pose and covariance are updated
        for observation_idx in range(number_obs):
            scores = np.zeros_like(number_pred)
            observation = z_i[observation_idx, :]

            for prediction_idx in range(number_pred):
                prediction = z_hat[prediction_idx, :]
                delta_z = observation - prediction

                # a set of likelihood scores is computed for each observation
                scores[prediction_idx] = scaling_factor[prediction_idx] * \
                                         np.exp(-0.5 * delta_z @ innovation_S_inv[prediction_idx, :, :] @ delta_z.T)

            # for each observed feature the index of the most likely among k features is retained
            most_likely_feature = np.argmax(scores)

            # compute Kalman gain for this observation
            kalman_gain = self.last_covariance @ jacobian_H[most_likely_feature, :, :].T \
                          @ innovation_S_inv[most_likely_feature, :, :]

            # correct pose and covariance with respect to this observation
            self.last_state_mu += kalman_gain * (observation - z_hat[most_likely_feature, :])
            self.last_covariance = (np.eye(3) - kalman_gain * jacobian_H[most_likely_feature, :, :]) \
                                   @ self.last_covariance

        return self.last_state_mu


class Localization:
    """
    Main node which handles incoming odometry data, control inputs from teleop, and features extracted by the package
    laser_line_extraction. Calls the Kalman Filter class to make a prediction of the system state and a correction on the
    basis of the measurement performed
    @input: odometry as nav_msgs Odometry message
    @input: line segments as custom LineSegmentList message, see package at https://github.com/kam3k/laser_line_extraction
    @output: pose as geometry_msgs PoseStamped message
    """

    def __init__(self, dt):
        """
        class initialization
        @param: self
        @param: rate - updating frequency for this node in [Hz]
        @result: get static parameters from parameter server
                 to initialize the controller, and to
                 set up publishers and subscribers
        """
        ### timing ###
        self.frequency = 20  # [Hz]
        self.dt = 1 / self.frequency  # [s]
        self.rate = rospy.Rate(self.frequency)  # timing object

        ### subscribers ###
        self.ground_truth_sub = rospy.Subscriber("/ground_truth", Odometry, self.groundTruthCallback)
        self.odom_sub = rospy.Subscriber("/odom", Odometry, self.odometryCallback)
        self.control_input_sub = rospy.Subscriber("/cmd_vel", Twist, self.controlInputCallback)
        self.line_segment_sub = rospy.Subscriber("/line_segments", LineSegmentList, self.lineListCallback)

        ### publishers ###
        self.pose_pub = rospy.Publisher("/robot_pose", PoseStamped,
                                        queue_size=1)  # queue_size=1 => only the newest map available

        self.map_features_pub = rospy.Publisher("/map_features", Marker,
                                        queue_size=1)  # queue_size=1 => only the newest map available

        ### initialize message to collect the list of extracted features ###
        self.line_list_msg = LineSegmentList()
        self.extracted_lines = None

        ### initialize KF class ###
        # could be initialized in first run of ground_truth callback
        # now it should be  -x 0 -y 0 -z 0, see line 31 in scitos.launch
        initial_pose = np.zeros((3, 1))
        self.kalman_filter = KalmanFilter(self.dt, initial_pose)

        ### initialization of class variables ###
        self.robot_pose_odom = None
        self.robot_pose_estimate = None
        self.odom_msg = None  # input
        self.ground_truth_msg = None  # input
        self.control_input = np.zeros((2, 1))  # [v, w]'

        ### predicted pose message ###
        self.predicted_state_msg = PoseStamped()
        self.predicted_state_msg.header = Header()
        self.predicted_state_msg.header.frame_id = "odom"
        self.predicted_state_msg.pose = Pose()
        self.predicted_state_msg.pose.position = Point()
        self.predicted_state_msg.pose.orientation = Quaternion()

        ### fetch map feature set from ROS parameters server ###
        self.map_features_raw = rospy.get_param("/map_features/")
        self.map_features_clean = {"start": [], "mid": [], "end": [], "length": [], "position1": [], "position2": []}

        # get map parameters for transformation of grid into world coordinates
        self.map_width = rospy.get_param("/map/width")
        self.map_height = rospy.get_param("/map/height")
        self.map_resolution = rospy.get_param("/map/resolution")
        self.map_origin = rospy.get_param("/map/origin")

        ### initialize the marker message & display settings ###
        self.features_marker_msg = Marker()
        self.features_marker_msg.ns = "line_extraction"
        self.features_marker_msg.id = 0
        self.features_marker_msg.type = np.int(5)  # display marker as line list
        self.features_marker_msg.scale.x = 0.1
        self.features_marker_msg.header = Header()
        self.features_marker_msg.header.frame_id = "odom"
        self.features_marker_msg.header.stamp = rospy.get_rostime()

        # extract coordinates of each individual feature in the set
        for point in range(0, len(self.map_features_raw["start_x"])):

            # filter out by trial and error the features that came out of the artefacts of the occupancy grid map

            if (int(self.map_features_raw["start_y"][point]) > 270 or int(self.map_features_raw["end_y"][point]) > 270) and \
                    (int(self.map_features_raw["start_x"][point]) < 230 and int(self.map_features_raw["end_x"][point]) < 230):
                continue

            if (int(self.map_features_raw["start_x"][point]) > 238 and int(self.map_features_raw["end_x"][point]) > 238):
                continue

            if int(self.map_features_raw["start_y"][point]) < 68 or int(self.map_features_raw["end_y"][point]) < 68:
                continue

            if (int(self.map_features_raw["start_x"][point]) < 41 or int(self.map_features_raw["end_x"][point]) < 41) and \
                    int(self.map_features_raw["start_y"][point]) > 270 or int(self.map_features_raw["end_y"][point]) > 270:
                continue

            if (int(self.map_features_raw["start_x"][point]) < 41 or int(self.map_features_raw["end_x"][point]) < 41) and \
                    (int(self.map_features_raw["start_y"][point]) < 250 and int(self.map_features_raw["end_y"][point]) < 250):
                continue

            if (int(self.map_features_raw["start_x"][point]) < 38 or int(self.map_features_raw["end_x"][point]) < 38) and \
                    (int(self.map_features_raw["start_y"][point]) > 250 and int(self.map_features_raw["end_y"][point]) < 260):
                continue

            # convert grid to world coordinates with +/- translation to center the features on the environment
            start_point = grid_to_world(int(self.map_features_raw["start_x"][point]) + 1,
                                        int(self.map_features_raw["start_y"][point]) - 1,
                                        self.map_origin[0], self.map_origin[1], self.map_width, self.map_height,
                                        self.map_resolution)

            end_point = grid_to_world(int(self.map_features_raw["end_x"][point]) + 1,
                                      int(self.map_features_raw["end_y"][point]) - 1,
                                      self.map_origin[0], self.map_origin[1],
                                      self.map_width, self.map_height, self.map_resolution)

            # assign color to each end point of the line segment
            color = ColorRGBA(0.0, 1.0, 0.0, 1.0)
            self.features_marker_msg.colors.append(color)
            self.features_marker_msg.colors.append(color)

            # add start point to list
            p_start = Point()
            p_start.x = start_point[0]
            p_start.y = -1*start_point[1]+0.66*self.map_width
            p_start.z = 0
            self.features_marker_msg.points.append(p_start)

            # add end point to list
            p_end = Point()
            p_end.x = end_point[0]
            p_end.y = -1*end_point[1]+0.66*self.map_width
            p_end.z = 0
            self.features_marker_msg.points.append(p_end)

            self.map_features_clean["start"].append(np.asarray(start_point))
            self.map_features_clean["end"].append(np.asarray(end_point))
            self.map_features_clean["mid"].append(np.array([round(start_point[0] + (end_point[0] - start_point[0]) / 2),
                                                            round(start_point[1] + (end_point[1] - start_point[1]) / 2)]).
                                                  reshape(1, 2))

            self.map_features_clean["length"].append(round(norm(np.array([end_point[0] - start_point[0],
                                                                          end_point[1] - start_point[1]])), 2))

        print(self.map_features_clean)


    def run(self):
        """
        Main loop of class.
        @param: self
        @result: runs the step function for the predicton and update steps.
        """
        while not rospy.is_shutdown():

            ### step only when odometry is available ###
            if self.odom_msg:
                self.step()

            # publish features
            self.features_marker_msg.header.stamp = rospy.get_rostime()
            self.map_features_pub.publish(self.features_marker_msg)

            # sleep to selected frequency
            self.rate.sleep()


    def step(self):
        """
        Perform an iteration of the localization loop.
        @param: self
        @result: performs the predicton and update steps. Publish pose estimate and map features.
        """
        self.robot_pose_estimate = self.kalman_filter.predictionStep(self.control_input)
        # self.lineExtraction()
        # self.robot_pose_estimate = self.kalman_filter.correctionStep(TBD)

        ### Message editing ###
        self.predicted_state_msg.pose.position.x = self.robot_pose_estimate[0, 0]
        self.predicted_state_msg.pose.position.y = self.robot_pose_estimate[1, 0]
        q = quaternion_from_euler(self.robot_pose_estimate[2, 0], 0, 0, 'rzyx')
        self.predicted_state_msg.pose.orientation.x = q[0]
        self.predicted_state_msg.pose.orientation.y = q[1]
        self.predicted_state_msg.pose.orientation.z = q[2]
        self.predicted_state_msg.pose.orientation.w = q[3]

        ### Publish ###
        self.pose_pub.publish(self.predicted_state_msg)


    def lineExtraction(self):

        nr_lines = len(self.line_list_msg.line_segments)
        # print("line nr: ", nr_lines)
        self.extracted_lines = np.zeros((nr_lines, 3))

        # extract each line contained in the message
        for line in range(0, nr_lines):
            print("line extraction started")

            # extract coordinates
            start = np.asarray(self.line_list_msg.line_segments[line].start)
            end = np.asarray(self.line_list_msg.line_segments[line].end)
            mid = np.array([round(start[0] + (end[0] - start[0]) / 2), round(start[1] + (end[1] - start[1]) / 2)])

            # assign mid point as target
            self.extracted_lines[line, 0] = mid[0]
            self.extracted_lines[line, 1] = mid[1]
            self.extracted_lines[line, 2] = norm(np.array([end[0]-start[0], end[1] - start[1]]))

            print("extracted line: ", self.extracted_lines[line, :])


    def lineListCallback(self, data):
        """
        Handles incoming LineSegmentList messages and saves the measurements
        @param: list of line segments stored in the LineSegmentList message
        @result: TBD
        """
        # save line list if any line was measured
        nr_lines = len(self.line_list_msg.line_segments)
        print("line nr: ", nr_lines)

        if len(self.line_list_msg.line_segments) > 0:
            nr_lines = len(self.line_list_msg.line_segments)
            print("line nr: ", nr_lines)
            self.line_list_msg = data


    def odometryCallback(self, data):
        """
        Handles incoming Odometry messages and performs a
        partial quaternion to euler angle transformation to get the yaw angle theta
        @param: pose data stored in the odometry message
        @result: global variables self.robot_pose containing the planar
                 coordinates (x,y)) and self.robot_yaw containing the yaw angle theta
        """
        self.odom_msg = data
        # extract yaw angle of robot pose using the transformation on the odometry message
        self.robot_yaw = euler_from_quaternion([data.pose.pose.orientation.x,
                                                data.pose.pose.orientation.y,
                                                data.pose.pose.orientation.z,
                                                data.pose.pose.orientation.w],
                                               axes='szyx')[0]
        # extract robot pose
        self.robot_pose_odom = [data.pose.pose.position.x, data.pose.pose.position.y]

    def groundTruthCallback(self, data):
        """
        Handles incoming groud truth messages
        @param: information from Gazebo
        @result: internal update of ground truth
        """
        self.ground_truth_msg = data

    def controlInputCallback(self, data):
        """
        Gets twist message from teleop_key.py and call prediction step of kalman filter
        @param: data of type Twist message
        @result: control input ndarray 2 x 1
        """
        # extract linear and angular velocities
        self.control_input = np.array([[data.linear.x],
                                       [data.angular.z]])


if __name__ == '__main__':
    # initialize node and name it
    rospy.init_node("LocalizationNode")  # should this be "LocalizationNode" right ? I changed it
    # go to class that provides all the functionality
    # and check for errors
    try:
        localization = Localization(10)
        localization.run()
    except rospy.ROSInterruptException:
        pass
